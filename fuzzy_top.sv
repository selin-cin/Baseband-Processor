module fuzzy_top #(
    parameter logic [23:0] HELPER_NVM_ADDR = 24'h000000
)(
    input  logic         clk_i,
    input  logic         rst_ni,

    input  logic         start_i,
    input  logic         mode_i,

    output logic         puf_ready_o,
    input  logic [59:0]  puf_data_i,
    input  logic         puf_valid_i,
    input  logic         puf_done_i,

    output logic [23:0]  nvm_address_o,
    output logic [31:0]  nvm_wdata_o,
    output logic         nvm_wvalid_o,
    input  logic         nvm_wready_i,

    input  logic [31:0]  nvm_rdata_i,
    input  logic         nvm_rvalid_i,
    output logic         nvm_rready_o,

    output logic [127:0] key_o,
    output logic         key_valid_o,

    output logic         busy_o,
    output logic         error_o,
    output logic         done_o
);

    typedef enum logic [2:0] {
        ST_IDLE,
        ST_REP_ENR,
        ST_BCH_ENR,
        ST_HASH_ENR,
        ST_REP_REC,
        ST_BCH_REC,
        ST_HASH_REC
    } state_t;

    state_t state_q, state_d;

    logic mode_q, mode_d;

    logic [254:0] rep_word_q, rep_word_d;

    logic [3:0]   r_rep_enc, r_rep_dec;
    logic [55:0]  h_rep_enc_flat;

    logic [191:0] tx_acc_q, tx_acc_d;
    logic [7:0]   tx_cnt_q, tx_cnt_d;

    logic [191:0] rx_acc_q, rx_acc_d;
    logic [7:0]   rx_cnt_q, rx_cnt_d;

    logic         enc_start_q, enc_start_d;
    logic         enc_kicked_q, enc_kicked_d;
    logic         enc_pushed_q, enc_pushed_d;
    logic [115:0] enc_parity_o;

    logic         dec_start_q, dec_start_d;
    logic         dec_kicked_q, dec_kicked_d;
    logic [115:0] rx_bch_mask_q, rx_bch_mask_d;
    logic [254:0] dec_word_i;
    logic [254:0] dec_corrected_o;
    logic [138:0] dec_k_o;
    logic         dec_fail_o, dec_done_o;

    logic         hash_start_q, hash_start_d;
    logic         hash_kicked_q, hash_kicked_d;
    logic [138:0] hash_msg_q, hash_msg_d;
    logic         hash_ready_o, hash_busy_o, hash_done_o, hash_digest_valid_o;
    logic [127:0] hash_digest_o;

    logic [127:0] key_q, key_d;
    logic         key_valid_q, key_valid_d;
    logic         error_q, error_d;
    logic         done_q, done_d;

    logic         enc_ready_o, enc_done_o;

    logic [250:0] rep_word_low;
    logic [138:0] rep_word_msg;
    logic [115:0] rep_word_upper;
    logic [115:0] rx_acc_low116;
    logic [31:0]  tx_acc_low32;

    assign rep_word_low   = rep_word_q[250:0];
    assign rep_word_msg   = rep_word_q[138:0];
    assign rep_word_upper = rep_word_q[254:139];
    assign rx_acc_low116  = rx_acc_q[115:0];
    assign tx_acc_low32   = tx_acc_q[31:0];

    assign nvm_address_o = HELPER_NVM_ADDR;
    assign busy_o         = (state_q != ST_IDLE);
    assign key_o          = key_q;
    assign key_valid_o    = key_valid_q;
    assign error_o        = error_q;
    assign done_o         = done_q;

    generate
        for (genvar g = 0; g < 4; g++) begin : g_rep
            repetition_encoder u_rep_enc (
                .enable_i  (puf_valid_i),
                .message_i (puf_data_i[g*15 +: 15]),
                .h_rep_o   (h_rep_enc_flat[g*14 +: 14]),
                .r_rep_o   (r_rep_enc[g]),
                .done_o    ()
            );
            repetition_decoder u_rep_dec (
                .enable_i    (puf_valid_i && !mode_q),
                .r_rep_i     (r_rep_enc[g]),
                .h_rep_enc_i (h_rep_enc_flat[g*14 +: 14]),
                .h_rep_nvm_i (rx_acc_q[g*14 +: 14]),
                .r_rep_o     (r_rep_dec[g])
            );
        end
    endgenerate

    bch_encoder u_bch_encoder (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),
        .start_i    (enc_start_q),
        .received_i (rep_word_q[138:0]),
        .parity_o   (enc_parity_o),
        .ready_o    (enc_ready_o),
        .done_o     (enc_done_o)
    );

    bch_decoder u_bch_decoder (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .start_i     (dec_start_q),
        .word_i      (dec_word_i),
        .corrected_o (dec_corrected_o),
        .k_o         (dec_k_o),
        .fail_o      (dec_fail_o),
        .done_o      (dec_done_o)
    );

    ascon_xof128_hardcoded u_ascon_hash (
        .clk_i          (clk_i),
        .rst_ni         (rst_ni),
        .start_i        (hash_start_q),
        .message_i      (hash_msg_q),
        .ready_o        (hash_ready_o),
        .busy_o         (hash_busy_o),
        .done_o         (hash_done_o),
        .digest_valid_o (hash_digest_valid_o),
        .digest_o       (hash_digest_o)
    );

    assign dec_word_i = { rep_word_q[138:0], (rep_word_q[254:139] ^ rx_bch_mask_q) };

    always_comb begin
        state_d       = state_q;
        mode_d        = mode_q;
        rep_word_d    = rep_word_q;

        tx_acc_d      = tx_acc_q;
        tx_cnt_d      = tx_cnt_q;
        rx_acc_d      = rx_acc_q;
        rx_cnt_d      = rx_cnt_q;

        enc_start_d   = 1'b0;
        enc_kicked_d  = enc_kicked_q;
        enc_pushed_d  = enc_pushed_q;

        dec_start_d   = 1'b0;
        dec_kicked_d  = dec_kicked_q;
        rx_bch_mask_d = rx_bch_mask_q;

        hash_start_d  = 1'b0;
        hash_kicked_d = hash_kicked_q;
        hash_msg_d    = hash_msg_q;

        key_d         = key_q;
        key_valid_d   = 1'b0;
        error_d       = 1'b0;
        done_d        = 1'b0;

        puf_ready_o   = 1'b0;
        nvm_wvalid_o  = 1'b0;
        nvm_rready_o  = 1'b0;

        case (state_q)

            ST_IDLE: begin
                tx_acc_d      = '0;
                tx_cnt_d      = 8'd0;
                rx_acc_d      = '0;
                rx_cnt_d      = 8'd0;
                enc_kicked_d  = 1'b0;
                enc_pushed_d  = 1'b0;
                dec_kicked_d  = 1'b0;
                rx_bch_mask_d = '0;
                hash_kicked_d = 1'b0;

                if (start_i) begin
                    mode_d     = mode_i;
                    rep_word_d = '0;
                    if (mode_i) begin
                        state_d = ST_REP_ENR;
                    end else begin
                        state_d = ST_REP_REC;
                    end
                end
            end

            ST_REP_ENR: begin
                nvm_wvalid_o = (tx_cnt_q != 8'd0);
                if (nvm_wvalid_o && nvm_wready_i) begin
                    tx_acc_d = tx_acc_q >> 32;
                    tx_cnt_d = (tx_cnt_q > 8'd32) ? (tx_cnt_q - 8'd32) : 8'd0;
                end

                puf_ready_o = !puf_done_i && (tx_cnt_q == 8'd0);

                if (puf_valid_i && puf_ready_o) begin
                    rep_word_d = {rep_word_low, r_rep_enc};
                    tx_acc_d   = {136'd0, h_rep_enc_flat};
                    tx_cnt_d   = 8'd56;
                end

                if (puf_done_i && (tx_cnt_q == 8'd0)) begin
                    state_d = ST_BCH_ENR;
                end
            end

            ST_BCH_ENR: begin
                nvm_wvalid_o = (tx_cnt_q != 8'd0);
                if (nvm_wvalid_o && nvm_wready_i) begin
                    tx_acc_d = tx_acc_q >> 32;
                    tx_cnt_d = (tx_cnt_q > 8'd32) ? (tx_cnt_q - 8'd32) : 8'd0;
                end

                enc_start_d = enc_ready_o && !enc_kicked_q;
                if (enc_start_d) begin
                    enc_kicked_d = 1'b1;
                end

                if (enc_done_o) begin
                    tx_acc_d     = {76'd0, (rep_word_upper ^ enc_parity_o)};
                    tx_cnt_d     = 8'd116;
                    enc_pushed_d = 1'b1;
                end

                if (enc_pushed_q && (tx_cnt_q == 8'd0)) begin
                    state_d = ST_HASH_ENR;
                end
            end

            ST_HASH_ENR: begin
                hash_msg_d   = rep_word_msg;
                hash_start_d = hash_ready_o && !hash_kicked_q;
                if (hash_start_d) begin
                    hash_kicked_d = 1'b1;
                end

                if (hash_digest_valid_o) begin
                    key_d       = hash_digest_o;
                    key_valid_d = 1'b1;
                    done_d      = 1'b1;
                    state_d     = ST_IDLE;
                end
            end

            ST_REP_REC: begin
                nvm_rready_o = (rx_cnt_q <= 8'd160);
                if (nvm_rvalid_i && nvm_rready_o) begin
                    rx_acc_d[rx_cnt_q +: 32] = nvm_rdata_i;
                    rx_cnt_d = rx_cnt_q + 8'd32;
                end

                puf_ready_o = !puf_done_i && (rx_cnt_q >= 8'd64);

                if (puf_valid_i && puf_ready_o) begin
                    rep_word_d = {rep_word_low, r_rep_dec};
                    rx_acc_d   = rx_acc_d >> 64;
                    rx_cnt_d   = rx_cnt_d - 8'd64;
                end

                if (puf_done_i) begin
                    state_d = ST_BCH_REC;
                end
            end

            ST_BCH_REC: begin
                nvm_rready_o = (rx_cnt_q <= 8'd160);
                if (nvm_rvalid_i && nvm_rready_o) begin
                    rx_acc_d[rx_cnt_q +: 32] = nvm_rdata_i;
                    rx_cnt_d = rx_cnt_q + 8'd32;
                end

                if (!dec_kicked_q && (rx_cnt_q >= 8'd128)) begin
                    rx_bch_mask_d = rx_acc_low116;
                    rx_acc_d      = rx_acc_d >> 128;
                    rx_cnt_d      = rx_cnt_d - 8'd128;
                    dec_start_d   = 1'b1;
                    dec_kicked_d  = 1'b1;
                end

                if (dec_done_o) begin
                    if (dec_fail_o) begin
                        error_d = 1'b1;
                        done_d  = 1'b1;
                        state_d = ST_IDLE;
                    end else begin
                        state_d = ST_HASH_REC;
                    end
                end
            end

            ST_HASH_REC: begin
                hash_msg_d   = dec_k_o;
                hash_start_d = hash_ready_o && !hash_kicked_q;
                if (hash_start_d) begin
                    hash_kicked_d = 1'b1;
                end

                if (hash_digest_valid_o) begin
                    key_d       = hash_digest_o;
                    key_valid_d = 1'b1;
                    done_d      = 1'b1;
                    state_d     = ST_IDLE;
                end
            end

            default: state_d = ST_IDLE;
        endcase

        nvm_wdata_o = tx_acc_low32;
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q       <= ST_IDLE;
            mode_q        <= 1'b0;
            rep_word_q    <= '0;
            tx_acc_q      <= '0;
            tx_cnt_q      <= 8'd0;
            rx_acc_q      <= '0;
            rx_cnt_q      <= 8'd0;
            enc_start_q   <= 1'b0;
            enc_kicked_q  <= 1'b0;
            enc_pushed_q  <= 1'b0;
            dec_start_q   <= 1'b0;
            dec_kicked_q  <= 1'b0;
            rx_bch_mask_q <= '0;
            hash_start_q  <= 1'b0;
            hash_kicked_q <= 1'b0;
            hash_msg_q    <= '0;
            key_q         <= '0;
            key_valid_q   <= 1'b0;
            error_q       <= 1'b0;
            done_q        <= 1'b0;
        end
        else begin
            state_q       <= state_d;
            mode_q        <= mode_d;
            rep_word_q    <= rep_word_d;
            tx_acc_q      <= tx_acc_d;
            tx_cnt_q      <= tx_cnt_d;
            rx_acc_q      <= rx_acc_d;
            rx_cnt_q      <= rx_cnt_d;
            enc_start_q   <= enc_start_d;
            enc_kicked_q  <= enc_kicked_d;
            enc_pushed_q  <= enc_pushed_d;
            dec_start_q   <= dec_start_d;
            dec_kicked_q  <= dec_kicked_d;
            rx_bch_mask_q <= rx_bch_mask_d;
            hash_start_q  <= hash_start_d;
            hash_kicked_q <= hash_kicked_d;
            hash_msg_q    <= hash_msg_d;
            key_q         <= key_d;
            key_valid_q   <= key_valid_d;
            error_q       <= error_d;
            done_q        <= done_d;
        end
    end

endmodule
